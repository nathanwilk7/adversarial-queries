SELECT count(*)
FROM aka_title, cast_info, char_name, company_type, link_type, movie_companies, movie_link, title
WHERE char_name.imdb_index = ''
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
