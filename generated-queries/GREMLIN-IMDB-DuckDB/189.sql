SELECT count(*)
FROM cast_info, comp_cast_type, company_type, complete_cast, keyword, link_type, movie_companies, movie_keyword, movie_link, name, title
WHERE comp_cast_type.kind = 'complete+verified'
  AND name.gender = 'm'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
