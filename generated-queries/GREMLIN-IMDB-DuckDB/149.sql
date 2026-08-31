SELECT count(*)
FROM cast_info, char_name, company_name, keyword, link_type, movie_companies, movie_keyword, movie_link, title
WHERE char_name.imdb_index = 'II'
  AND title.production_year < 2003
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
