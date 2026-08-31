SELECT count(*)
FROM cast_info, char_name, company_type, keyword, kind_type, movie_companies, movie_keyword, movie_link, title
WHERE char_name.imdb_index = 'II'
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
