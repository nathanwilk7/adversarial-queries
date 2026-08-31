SELECT count(*)
FROM aka_title, cast_info, company_type, movie_companies, movie_link, name, role_type, title
WHERE company_type.kind = 'special effects companies'
  AND name.imdb_index = 'XC'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
